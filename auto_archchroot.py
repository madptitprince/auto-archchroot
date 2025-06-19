#!/usr/bin/env python3
"""
Auto Arch-Chroot Generator
Génère automatiquement un script perform-chroot.sh basé sur la configuration système actuelle.
Supporte ext4, btrfs, LUKS, sous-volumes btrfs, et configurations complexes.
"""

import os
import sys
import re
import json
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import configparser

def setup_logging():
    """Configure le systeme de logging"""
    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/var/log/auto-archchroot.log'),
                logging.StreamHandler()
            ]
        )
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )

@dataclass
class MountPoint:
    """Point de montage"""
    device: str
    mount_point: str
    fs_type: str
    options: List[str] = field(default_factory=list)
    uuid: Optional[str] = None
    is_luks: bool = False
    luks_device: Optional[str] = None
    btrfs_subvol: Optional[str] = None
    order: int = 0


setup_logging()
logger = logging.getLogger(__name__)
class SystemAnalyzer:
    """Analyse le système actuel pour générer le script de chroot"""

    def __init__(self):
        self.luks_devices: Dict[str, str] = {}
        self.btrfs_subvolumes: Dict[str, List[str]] = {}
    
    def run_command(self, cmd: List[str]) -> Tuple[str, int]:
        """Exécute une commande et retourne stdout et code de retour"""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return result.stdout.strip(), result.returncode
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de {' '.join(cmd)}: {e}")
            return "", 1
    
    def get_device_info(self) -> Dict[str, Dict]:
        """Récupère les informations sur tous les périphériques de stockage"""
        devices = {}
        cmd = ['lsblk', '-J', '-o', 'NAME,UUID,FSTYPE,MOUNTPOINT,SIZE,TYPE']
        output, code = self.run_command(cmd)
        
        if code == 0:
            try:
                data = json.loads(output)
                for device in data.get('blockdevices', []):
                    self._process_device(device, devices)
            except json.JSONDecodeError as e:
                logger.error(f"Erreur parsing JSON lsblk: {e}")
        return devices
    
    def _process_device(self, device: dict, devices: dict, parent_name: str = ""):
        """Traite récursivement les informations d'un périphérique"""
        name = device.get('name', '')
        full_name = f"/dev/{name}"
        devices[full_name] = {
            'uuid': device.get('uuid'),
            'fstype': device.get('fstype'),
            'mountpoint': device.get('mountpoint'),
            'size': device.get('size'),
            'type': device.get('type')
        }
        for child in device.get('children', []):
            self._process_device(child, devices, name)
    
    def detect_luks_devices(self) -> Dict[str, str]:
        """Détecte les périphériques LUKS et leurs mappings"""
        luks_devices = {}
        cmd = ['blkid', '-t', 'TYPE=crypto_LUKS']
        output, code = self.run_command(cmd)
        
        if code == 0:
            for line in output.split('\n'):
                if line.strip():
                    match = re.match(r'^([^:]+):\s+UUID="([^"]+)".*TYPE="crypto_LUKS"', line)
                    if match:
                        device, uuid = match.groups()
                        luks_devices[uuid] = device
                        logger.info(f"Périphérique LUKS détecté: {device} (UUID: {uuid})")
        
        return luks_devices
    
    def detect_btrfs_subvolumes(self, device: str) -> List[str]:
        """Détecte les sous-volumes btrfs sur un périphérique"""
        subvolumes = []
        temp_mount = "/tmp/btrfs_temp_mount"
        os.makedirs(temp_mount, exist_ok=True)
        try:
            mount_cmd = ['mount', device, temp_mount]
            _, code = self.run_command(mount_cmd)
            
            if code == 0:
                subvol_cmd = ['btrfs', 'subvolume', 'list', temp_mount]
                output, code = self.run_command(subvol_cmd)
                
                if code == 0:
                    for line in output.split('\n'):
                        if line.strip():
                            match = re.search(r'path\s+(.+)$', line)
                            if match:
                                subvol_path = match.group(1)
                                subvolumes.append(subvol_path)
                                logger.info(f"Sous-volume btrfs trouvé: {subvol_path}")
        finally:
            self.run_command(['umount', temp_mount])
            try:
                os.rmdir(temp_mount)
            except:
                pass

        return subvolumes
    
    def _detect_luks_for_uuid(self, uuid: str, luks_devices: Dict[str, str]) -> Tuple[bool, Optional[str]]:
        """
        Détecte si un UUID correspond à un périphérique LUKS
        Args:
            uuid: UUID à vérifier
            luks_devices: Mapping des UUIDs LUKS
        Returns:
            Tuple (is_luks, luks_device_path)
        """
        if uuid in luks_devices:
            return True, luks_devices[uuid]
        return False, None
    
    def _detect_luks_for_mapper(self, device: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Détecte les informations LUKS pour un périphérique /dev/mapper/
        Args:
            device: Chemin du périphérique mapper
        Returns:
            Tuple (is_luks, luks_device_path, uuid)
        """
        dm_name = device.split('/')[-1]
        luks_cmd = ['cryptsetup', 'status', dm_name]
        output, code = self.run_command(luks_cmd)
        
        if code != 0 or 'is active' not in output:
            return False, None, None
        match = re.search(r'device:\s+(/dev/\S+)', output)
        if not match:
            return True, None, None

        luks_device = match.group(1)
        uuid_cmd = ['blkid', '-o', 'value', '-s', 'UUID', luks_device]
        uuid_output, uuid_code = self.run_command(uuid_cmd)
        uuid = uuid_output.strip() if uuid_code == 0 and uuid_output else None
        
        return True, luks_device, uuid
    
    def _extract_btrfs_subvolume(self, options: List[str]) -> Optional[str]:
        """
        Extrait le nom du sous-volume btrfs des options de montage
        Args:
            options: Liste des options de montage
        Returns:
            Nom du sous-volume ou None
        """
        for opt in options:
            if opt.startswith('subvol='):
                return opt[7:]
        return None
    
    def _parse_fstab_line(self, line: str, line_num: int) -> Optional[Tuple[str, str, str, List[str]]]:
        """
        Parse une ligne fstab et retourne (device, mount_point, fs_type, options)
        Args:
            line: Ligne à parser
            line_num: Numéro de ligne pour les messages d'erreur  
        Returns:
            Tuple (device, mount_point, fs_type, options) ou None si ligne invalide
        """
        line = line.strip()
        # Ignore empty lines and comments
        if not line or line.startswith('#'):
            return None
        parts = line.split()
        if len(parts) < 4:
            logger.warning(f"Ligne fstab invalide {line_num}: {line}")
            return None
        device = parts[0]
        mount_point = parts[1]
        fs_type = parts[2]
        options = parts[3].split(',')
        
        # Valide les champs critiques
        if not self._is_valid_fstab_entry(device, mount_point, fs_type):
            return None
        
        return device, mount_point, fs_type, options
    
    def _is_valid_fstab_entry(self, device: str, mount_point: str, fs_type: str) -> bool:
        """
        Valide une entrée fstab
        Args:
            device: Périphérique source
            mount_point: Point de montage
            fs_type: Type de système de fichiers
        Returns:
            True si l'entrée est valide pour notre usage
        """
        #skip special mount points
        if mount_point in ['none', 'swap'] or fs_type in ['swap', 'tmpfs', 'proc', 'sysfs', 'devtmpfs']:
            return False
        
        #tmp and virtual
        if fs_type in ['cgroup', 'cgroup2', 'securityfs', 'debugfs', 'configfs']:
            return False

        valid_device_prefixes = ['UUID=', 'LABEL=', '/dev/', 'PARTUUID=', 'PARTLABEL=']
        if not any(device.startswith(prefix) for prefix in valid_device_prefixes):
            logger.warning(f"Format de périphérique non supporté: {device}")
            return False
        
        return True
    
    def _resolve_device_uuid(self, uuid: str, device_info: Dict[str, Dict]) -> Optional[str]:
        """
        Résout un UUID vers un chemin de périphérique
        
        Args:
            uuid: UUID à résoudre
            device_info: Informations sur les périphériques
            
        Returns:
            Chemin du périphérique ou None si non trouvé
        """
        for dev_path, dev_info in device_info.items():
            if dev_info.get('uuid') == uuid:
                return dev_path
        return None

    def _create_mount_point(self, device: str, mount_point: str, fs_type: str, 
                          options: List[str], device_info: Dict[str, Dict], 
                          luks_devices: Dict[str, str]) -> MountPoint:
        """
        Crée un objet MountPoint à partir des informations parsées
        Args:
            device: Périphérique source
            mount_point: Point de montage
            fs_type: Type de système de fichiers
            options: Options de montage
            device_info: Informations sur les périphériques
            luks_devices: Mapping des périphériques LUKS
        Returns:
            Objet MountPoint configuré
        """
        mp = MountPoint(
            device=device,
            mount_point=mount_point,
            fs_type=fs_type,
            options=options,
            order=self._get_mount_order(mount_point)
        )
        
        #uuid handling
        if device.startswith('UUID='):
            uuid = device[5:]
            mp.uuid = uuid
            #uuid to device res
            resolved_device = self._resolve_device_uuid(uuid, device_info)
            if resolved_device:
                mp.device = resolved_device
            #luks check
            is_luks, luks_device = self._detect_luks_for_uuid(uuid, luks_devices)
            if is_luks:
                mp.is_luks = True
                mp.luks_device = luks_device
        #/dev/mapper/ handling
        elif device.startswith('/dev/mapper/'):
            is_luks, luks_device, uuid = self._detect_luks_for_mapper(device)
            if is_luks:
                mp.is_luks = True
                mp.luks_device = luks_device
                if uuid:
                    mp.uuid = uuid
        #btrfs handling
        if fs_type == 'btrfs':
            subvol = self._extract_btrfs_subvolume(options)
            if subvol:
                mp.btrfs_subvol = subvol
        return mp
    
    def parse_fstab(self, fstab_path: str = "/etc/fstab") -> List[MountPoint]:
        """
        Parse le fichier fstab et crée la liste des points de montage
        Args:
            fstab_path: Chemin vers le fichier fstab
        Returns:
            Liste des points de montage triée par ordre de montage
        Raises:
            FileNotFoundError: Si le fichier fstab n'existe pas
            PermissionError: Si le fichier n'est pas accessible
        """

        if not os.path.exists(fstab_path):
            raise FileNotFoundError(f"Fichier fstab non trouvé: {fstab_path}")
    
        mount_points = []
        #get sys info
        try:
            device_info = self.get_device_info()
            luks_devices = self.detect_luks_devices()
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des informations système: {e}")
            device_info = {}
            luks_devices = {}
        #fstab parsing
        try:
            with open(fstab_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    parsed = self._parse_fstab_line(line, line_num)
                    if parsed is None:
                        continue
                    device, mount_point, fs_type, options = parsed
                    try:
                        mp = self._create_mount_point(
                            device, mount_point, fs_type, options, 
                            device_info, luks_devices
                        )
                        mount_points.append(mp)
                        logger.info(f"Point de montage trouvé: {mp.mount_point} ({mp.device})")
                    except Exception as e:
                        logger.error(f"Erreur lors du traitement de la ligne {line_num}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Erreur lors de la lecture de {fstab_path}: {e}")
            raise
        #sort mp by order
        mount_points.sort(key=lambda x: x.order)
        return mount_points

    def _get_mount_order(self, mount_point: str) -> int:
        """Détermine l'ordre de montage basé sur la hiérarchie des points de montage"""
        order_map = {
            '/': 0,
            '/boot': 10,
            '/boot/efi': 11,
            '/home': 20,
            '/var': 21,
            '/usr': 22,
            '/opt': 23,
            '/tmp': 24
        }
        if mount_point in order_map:
            return order_map[mount_point]
        #for custom mount points, heuristic on depth
        return 30 + len(mount_point.split('/'))

class ScriptGenerator:
    """Génère le script perform-chroot.sh"""
    def __init__(self, mount_points: List[MountPoint]):
        self.mount_points = mount_points
        self.script_lines = []
    
    def generate_script(self, output_path: str = "/usr/local/bin/perform-chroot.sh"):
        """Génère le script complet"""
        self.script_lines = []        
        self._add_header()        
        self._add_utility_functions()    
        self._add_luks_handling()  
        self._add_filesystem_mounting()    
        self._add_pseudo_filesystems()       
        self._add_chroot_execution()
        self._add_cleanup()

        try:
            with open(output_path, 'w') as f:
                f.write('\n'.join(self.script_lines))
            
            os.chmod(output_path, 0o755)
            logger.info(f"Script généré avec succès: {output_path}")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'écriture du script: {e}")
            raise
    
    def _add_header(self):
        """Ajoute l'en-tête du script"""
        self.script_lines.extend([
            "#!/bin/bash",
            "# Généré automatiquement par auto-archchroot",
            f"# Date de génération: {subprocess.run(['date'], capture_output=True, text=True).stdout.strip()}",
            "",
            "set -euo pipefail",
            "",
            "# Couleurs pour les messages",
            'RED="\\033[31m"',
            'GREEN="\\033[32m"',
            'YELLOW="\\033[33m"',
            'BLUE="\\033[34m"',
            'RESET="\\033[0m"',
            "",
            "# Point de montage de base",
            "MOUNT_ROOT=\"/mnt\"",
            "",
            "# Vérification des privilèges root",
            "if [[ $EUID -ne 0 ]]; then",
            '    echo -e "${RED}Ce script doit être exécuté en tant que root${RESET}"',
            "    exit 1",
            "fi",
            ""
        ])
    
    def _add_utility_functions(self):
        """Ajoute les fonctions utilitaires"""
        self.script_lines.extend([
            "# Fonctions utilitaires",
            "log_info() {",
            '    echo -e "${BLUE}[INFO]${RESET} $1"',
            "}",
            "",
            "log_success() {",
            '    echo -e "${GREEN}[SUCCESS]${RESET} $1"',
            "}",
            "",
            "log_warning() {",
            '    echo -e "${YELLOW}[WARNING]${RESET} $1"',
            "}",
            "",
            "log_error() {",
            '    echo -e "${RED}[ERROR]${RESET} $1"',
            "}",
            "",
            "check_device_exists() {",
            "    local device=\"$1\"",
            "    if [[ ! -e \"$device\" ]]; then",
            '        log_error "Périphérique non trouvé: $device"',
            "        return 1",
            "    fi",
            "    return 0",
            "}",
            "",
            "create_mount_point() {",
            "    local mount_point=\"$1\"",
            "    if [[ ! -d \"$mount_point\" ]]; then",
            "        mkdir -p \"$mount_point\"",
            '        log_info "Point de montage créé: $mount_point"',
            "    fi",
            "}",
            ""
        ])
    
    def _add_luks_handling(self):
        """Ajoute la gestion des périphériques LUKS"""
        luks_devices = [mp for mp in self.mount_points if mp.is_luks]
        
        if not luks_devices:
            return
        
        self.script_lines.extend([
            "# Gestion des périphériques LUKS",
            "unlock_luks_devices() {",
            "    log_info \"Déverrouillage des périphériques LUKS...\"",
            ""
        ])
        
        for mp in luks_devices:
            luks_name = f"luks_{mp.uuid[:8]}" if mp.uuid else "luks_device"
            self.script_lines.extend([
                f"    # Déverrouillage de {mp.luks_device}",
                f"    if ! cryptsetup status {luks_name} >/dev/null 2>&1; then",
                f"        log_info \"Déverrouillage de {mp.luks_device}...\"",
                f"        cryptsetup open {mp.luks_device} {luks_name}",
                f"        log_success \"Périphérique LUKS déverrouillé: {luks_name}\"",
                f"    else",
                f"        log_info \"Périphérique LUKS déjà déverrouillé: {luks_name}\"",
                f"    fi",
                ""
            ])
        
        self.script_lines.extend([
            "}",
            ""
        ])
    
    def _add_filesystem_mounting(self):
        """Ajoute le montage des systèmes de fichiers"""
        self.script_lines.extend([
            "# Montage des systèmes de fichiers",
            "mount_filesystems() {",
            "    log_info \"Montage des systèmes de fichiers...\"",
            ""
        ])
        
        for mp in self.mount_points:
            mount_target = f"$MOUNT_ROOT{mp.mount_point}"
            
            if mp.is_luks:
                luks_name = f"luks_{mp.uuid[:8]}" if mp.uuid else "luks_device"
                source_device = f"/dev/mapper/{luks_name}"
            else:
                source_device = mp.device
            
            self.script_lines.extend([
                f"    # Montage de {mp.mount_point}",
                f"    check_device_exists \"{source_device}\"",
                f"    create_mount_point \"{mount_target}\"",
                ""
            ])
            
            mount_cmd = f"mount"
            
            mount_options = []
            if mp.btrfs_subvol:
                mount_options.append(f"subvol={mp.btrfs_subvol}")
            
            for opt in mp.options:
                if opt not in ['defaults', 'rw', 'auto', 'user', 'exec', 'suid']:
                    if not opt.startswith('subvol='): 
                        mount_options.append(opt)
            
            if mount_options:
                mount_cmd += f" -o {','.join(mount_options)}"
            
            mount_cmd += f" \"{source_device}\" \"{mount_target}\""
            
            self.script_lines.extend([
                f"    if ! mountpoint -q \"{mount_target}\"; then",
                f"        {mount_cmd}",
                f"        log_success \"Monté: {mp.mount_point}\"",
                f"    else",
                f"        log_info \"Déjà monté: {mp.mount_point}\"",
                f"    fi",
                ""
            ])
        
        self.script_lines.extend([
            "}",
            ""
        ])
    
    def _add_pseudo_filesystems(self):
        """Ajoute le montage des pseudo-systèmes de fichiers"""
        pseudo_fs = [
            ("/dev", "/dev"),
            ("/proc", "/proc"),
            ("/sys", "/sys"),
            ("/run", "/run")
        ]
        
        self.script_lines.extend([
            "# Montage des pseudo-systèmes de fichiers",
            "mount_pseudo_filesystems() {",
            "    log_info \"Montage des pseudo-systèmes de fichiers...\"",
            ""
        ])
        
        for source, target in pseudo_fs:
            mount_target = f"$MOUNT_ROOT{target}"
            self.script_lines.extend([
                f"    create_mount_point \"{mount_target}\"",
                f"    if ! mountpoint -q \"{mount_target}\"; then",
                f"        mount --bind \"{source}\" \"{mount_target}\"",
                f"        log_success \"Pseudo-FS monté: {target}\"",
                f"    fi"
            ])
        
        self.script_lines.extend([
            "",
            "    # Montage spécial pour /dev/pts si nécessaire",
            "    if [[ -d \"$MOUNT_ROOT/dev/pts\" ]] && ! mountpoint -q \"$MOUNT_ROOT/dev/pts\"; then",
            "        mount -t devpts devpts \"$MOUNT_ROOT/dev/pts\"",
            "    fi",
            "",
            "}",
            ""
        ])
    
    def _add_chroot_execution(self):
        """Ajoute l'exécution du chroot"""
        self.script_lines.extend([
            "# Exécution du chroot",
            "execute_chroot() {",
            "    log_info \"Entrée dans l'environnement chroot...\"",
            "    log_info \"Vous êtes maintenant dans l'environnement chroot du système installé.\"",
            "    log_info \"Pour sortir, tapez 'exit' ou appuyez sur Ctrl+D\"",
            "    ",
            "    # Copie le resolv.conf pour la résolution DNS",
            "    if [[ -f \"/etc/resolv.conf\" ]]; then",
            "        cp \"/etc/resolv.conf\" \"$MOUNT_ROOT/etc/resolv.conf\"",
            "    fi",
            "    ",
            "    # Entre dans le chroot",
            "    arch-chroot \"$MOUNT_ROOT\"",
            "    ",
            "    log_success \"Sortie du chroot\"",
            "}",
            ""
        ])
    
    def _add_cleanup(self):
        """Ajoute les fonctions de nettoyage"""
        self.script_lines.extend([
            "# Fonction de nettoyage",
            "cleanup() {",
            "    log_info \"Nettoyage en cours...\"",
            "    ",
            "    # Démonte les pseudo-systèmes de fichiers",
            "    for mount_point in \"/dev/pts\" \"/dev\" \"/proc\" \"/sys\" \"/run\"; do",
            "        full_path=\"$MOUNT_ROOT$mount_point\"",
            "        if mountpoint -q \"$full_path\"; then",
            "            umount \"$full_path\" 2>/dev/null || true",
            "        fi",
            "    done",
            "    ",
            "    # Démonte les systèmes de fichiers dans l'ordre inverse",
        ])
        
        for mp in reversed(self.mount_points):
            mount_target = f"$MOUNT_ROOT{mp.mount_point}"
            self.script_lines.extend([
                f"    if mountpoint -q \"{mount_target}\"; then",
                f"        umount \"{mount_target}\" 2>/dev/null || true",
                f"        log_info \"Démonté: {mp.mount_point}\"",
                f"    fi"
            ])
        
        luks_devices = [mp for mp in self.mount_points if mp.is_luks]
        if luks_devices:
            self.script_lines.append("\n    # Fermeture des périphériques LUKS")
            for mp in luks_devices:
                luks_name = f"luks_{mp.uuid[:8]}" if mp.uuid else "luks_device"
                self.script_lines.extend([
                    f"    if cryptsetup status {luks_name} >/dev/null 2>&1; then",
                    f"        cryptsetup close {luks_name} 2>/dev/null || true",
                    f"        log_info \"Fermé: {luks_name}\"",
                    f"    fi"
                ])
        
        self.script_lines.extend([
            "    ",
            "    log_success \"Nettoyage terminé\"",
            "}",
            "",
            "# Gestion des signaux pour le nettoyage",
            "trap cleanup EXIT INT TERM",
            "",
            "# Fonction principale",
            "main() {",
            "    log_info \"=== Démarrage de l'auto arch-chroot ===\"",
            "    ",
        ])
        
        if any(mp.is_luks for mp in self.mount_points):
            self.script_lines.append("    unlock_luks_devices")
        
        self.script_lines.extend([
            "    mount_filesystems",
            "    mount_pseudo_filesystems",
            "    execute_chroot",
            "}",
            "",
            "# Exécution du script principal",
            "main \"$@\""
        ])