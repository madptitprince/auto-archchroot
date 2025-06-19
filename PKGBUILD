pkgname=auto-archchroot
pkgver=1.0.0
pkgrel=1
pkgdesc="Génère automatiquement un script arch-chroot basé sur la configuration système"
arch=('any')
url="https://github.com/madptitprince/auto-archchroot"
license=('GPL3')
depends=('python' 'systemd' 'util-linux' 'btrfs-progs' 'cryptsetup')
optdepends=(
    'arch-install-scripts: pour arch-chroot'
    'gptfdisk: pour la gestion avancée des partitions'
    'os-prober: pour la détection automatique des systèmes'
)
backup=('etc/auto-archchroot/config.conf')
source=(
    "auto_archchroot.py"
    "auto-archchroot.service"
    "config.conf"
    "README.md"
    "auto-archchroot.8"
)
sha256sums=(
    'SKIP'  
    'SKIP'
    'SKIP'
    'SKIP'
    'SKIP'
)

package() {
    install -Dm755 "$srcdir/auto_archchroot.py" "$pkgdir/usr/local/bin/auto_archchroot.py"
    
    install -Dm644 "$srcdir/auto-archchroot.service" "$pkgdir/usr/lib/systemd/system/auto-archchroot.service"
    
    install -Dm644 "$srcdir/config.conf" "$pkgdir/etc/auto-archchroot/config.conf"
    
    install -Dm644 "$srcdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 "$srcdir/auto-archchroot.8" "$pkgdir/usr/share/man/man8/auto-archchroot.8"
    
    install -dm755 "$pkgdir/var/log"
    
    install -dm755 "$pkgdir/usr/bin"
    ln -sf "/usr/local/bin/auto_archchroot.py" "$pkgdir/usr/bin/auto-archchroot"
}

post_install() {
    echo "==> Auto Arch-Chroot installé avec succès!"
    echo ""
    echo "Pour activer le service qui génère automatiquement le script à l'arrêt:"
    echo "  sudo systemctl enable auto-archchroot.service"
    echo ""
    echo "Pour générer immédiatement le script perform-chroot.sh:"
    echo "  sudo auto-archchroot"
    echo ""
    echo "Le script généré sera disponible à:"
    echo "  /home/perform-chroot.sh"
    echo ""
    echo "Configuration disponible dans:"
    echo "  /etc/auto-archchroot/config.conf"
    echo ""
    echo "Logs disponibles dans:"
    echo "  /var/log/auto-archchroot.log"
}

post_upgrade() {
    echo "==> Auto Arch-Chroot mis à jour!"
    echo ""
    echo "N'oubliez pas de redémarrer le service si nécessaire:"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl restart auto-archchroot.service"
}

pre_remove() {
    if systemctl is-enabled auto-archchroot.service >/dev/null 2>&1; then
        systemctl disable auto-archchroot.service
    fi
    
    if systemctl is-active auto-archchroot.service >/dev/null 2>&1; then
        systemctl stop auto-archchroot.service
    fi
}

post_remove() {
    echo "==> Auto Arch-Chroot supprimé"
    echo ""
    echo "Les fichiers suivants ont été conservés et peuvent être supprimés manuellement:"
    echo "  /var/log/auto-archchroot.log"
    echo "  /home/perform-chroot.sh (script généré)"
    echo "  /etc/auto-archchroot/ (configuration personnalisée)"
}