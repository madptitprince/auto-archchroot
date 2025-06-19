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
    