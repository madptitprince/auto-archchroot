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