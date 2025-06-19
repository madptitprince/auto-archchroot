# Auto Arch-Chroot

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Arch Linux](https://img.shields.io/badge/Arch%20Linux-1793D1?logo=arch-linux&logoColor=fff)](https://aur.archlinux.org/packages/auto-archchroot)

Génère automatiquement un script `perform-chroot.sh` intelligent basé sur la configuration actuelle de votre système Arch Linux. Ce script permet de reproduire facilement le processus d'`arch-chroot` depuis un live USB, en gérant automatiquement les configurations complexes.

## Fonctionnalités

### Support Complet des Configurations
- **Systèmes de fichiers classiques** : ext4, xfs, f2fs
- **Btrfs avancé** : Détection automatique des sous-volumes
- **Chiffrement LUKS** : Déverrouillage automatique des volumes chiffrés
- **Configurations hybrides** : Btrfs + LUKS, multi-partitions, etc.

### Automatisation Intelligente
- **Service systemd** : Génération automatique à l'extinction du système
- **Analyse en temps réel** : Parse `/etc/fstab` et détecte la configuration matérielle
- **Gestion d'erreurs robuste** : Vérifications et fallbacks intelligents
- **Nettoyage automatique** : Démontage propre en cas d'interruption

### Sécurité et Robustesse
- **Vérification des périphériques** : S'assure de l'existence des volumes avant montage
- **Gestion des permissions** : Contrôles de sécurité intégrés
- **Sauvegarde automatique** : Conserve les anciens scripts
- **Logs détaillés** : Traçabilité complète des opérations

## Installation

### Depuis l'AUR (à venir)
```bash
# Avec yay
yay -S auto-archchroot

paru -S auto-archchroot

# Manuellement
git clone https://aur.archlinux.org/auto-archchroot.git
cd auto-archchroot
makepkg -si
```

### Installation Manuelle
```bash
git clone https://github.com/madptitprince/auto-archchroot.git
cd auto-archchroot
makepkg -si
```

## Utilisation

### Activation du Service Automatique
```bash
sudo systemctl enable auto-archchroot.service

sudo systemctl start auto-archchroot.service
```

### Génération Manuelle
```bash
# Génère immédiatement le script
sudo auto-archchroot

```

### Utilisation du Script Généré
Depuis un live USB Arch Linux :
```bash
chmod +x perform-chroot.sh

sudo ./perform-chroot.sh
```

## 🧪 Configurations Testées

| Système de Fichiers | Non Chiffré | LUKS |
|-------------------|-------------|------|
| **ext4**          | ✅         | ✅   |
| **btrfs**         | ✅ (sous-volumes) | ✅ (sous-volumes + LUKS) |
| **xfs**           | ✅         | ✅   |
| **f2fs**          | ✅         | ✅   |

### Exemples de Configurations Supportées

#### Btrfs avec Sous-volumes
```bash
UUID=12345678-1234-1234-1234-123456789012 /     btrfs subvol=@,compress=zstd,noatime 0 1
UUID=12345678-1234-1234-1234-123456789012 /home btrfs subvol=@home,compress=zstd,noatime 0 2
UUID=87654321-4321-4321-4321-210987654321 /boot ext4  defaults 0 2
```

#### LUKS + Btrfs
```bash
UUID=luks-uuid-here / btrfs subvol=@,compress=zstd 0 1
UUID=boot-uuid-here /boot ext4 defaults 0 2
UUID=efi-uuid-here /boot/efi vfat defaults 0 2
```

## Configuration

Le fichier de configuration principal se trouve dans `/etc/auto-archchroot/config.conf` :

```ini
[general]
output_script_path = /home/perform-chroot.sh
fstab_path = /etc/fstab
mount_root = /mnt
log_level = INFO

[luks]
device_prefix = luks_
unlock_timeout = 30
max_attempts = 3

[btrfs]
auto_detect_subvolumes = true
default_subvol_options = compress=zstd,noatime

[script]
colored_output = true
auto_cleanup = true
copy_resolv_conf = true
```

## Script Généré

Le script `perform-chroot.sh` généré inclut :

### Fonctionnalités Automatiques
- **Déverrouillage LUKS** : Demande les mots de passe si nécessaire
- **Montage hiérarchique** : Monte dans l'ordre correct (/, /boot, /boot/efi, etc.)
- **Sous-volumes Btrfs** : Applique automatiquement les bonnes options
- **Pseudo-systèmes** : Monte /dev, /proc, /sys, /run
- **Réseau** : Copie resolv.conf pour la connectivité
- **Nettoyage** : Démonte tout proprement à la sortie

### Exemple de Script Généré
```bash
#!/bin/bash
# Généré automatiquement par auto-archchroot

cryptsetup open /dev/sda2 luks_12345678

mount -o subvol=@ /dev/mapper/luks_12345678 /mnt

mount /dev/sda1 /mnt/boot

mount --bind /dev /mnt/dev
mount --bind /proc /mnt/proc
mount --bind /sys /mnt/sys
mount --bind /run /mnt/run

arch-chroot /mnt
```

## Dépannage

### Problèmes Courants

#### Le service ne démarre pas
```bash
sudo systemctl status auto-archchroot.service

# Voir les logs
sudo journalctl -u auto-archchroot.service

# Vérifier la configuration
sudo auto-archchroot --dry-run
```

#### Script non généré
```bash
# Vérifier les permissions
ls -la /usr/local/bin/auto_archchroot.py

# Tester manuellement
sudo python3 /usr/local/bin/auto_archchroot.py

cat /etc/fstab
```

#### Erreurs de montage
```bash
sudo blkid

sudo cryptsetup status

sudo btrfs subvolume list /
```

### Logs et Debug

Les logs sont disponibles dans `/var/log/auto-archchroot.log` :

```bash
tail -f /var/log/auto-archchroot.log

grep ERROR /var/log/auto-archchroot.log

sudo auto-archchroot --debug
```


## Contribution

Les contributions sont les bienvenues ! Merci de :

1. **Fork** le projet
2. **Créer** une branche pour votre fonctionnalité (`git checkout -b feature/AmazingFeature`)
3. **Commit** vos changements (`git commit -m 'Add some AmazingFeature'`)
4. **Push** vers la branche (`git push origin feature/AmazingFeature`)
5. **Ouvrir** une Pull Request

### Tests Requis
Avant de soumettre, assurez-vous que :
- [ ] Les tests passent sur les 4 configurations (ext4/btrfs × plain/LUKS)
- [ ] Le code respecte PEP 8
- [ ] La documentation est à jour
- [ ] Les logs sont appropriés

## Licence

Ce projet est sous licence GPL v3. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## 🙏 Remerciements

- **Arch Linux** pour l'excellente distribution
- **Communauté Btrfs** pour la documentation des sous-volumes
- **Développeurs systemd** pour les services robustes
- **Contributeurs** qui améliorent ce projet

## Support

- **Issues GitHub** : [Signaler un bug](https://github.com/madptitprince/auto-archchroot/issues)
- **Discussions** : [Forum Arch](https://bbs.archlinux.org/)
- **AUR Comments** : [Page AUR](https://aur.archlinux.org/packages/auto-archchroot)

---

**Auto Arch-Chroot** - Simplifiez votre workflow de récupération système ! 🚀