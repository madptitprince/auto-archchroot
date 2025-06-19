import pytest

from auto_archchroot import SystemAnalyzer
from auto_archchroot import MountPoint

sys_analyser = SystemAnalyzer()

@pytest.fixture

def test_get_device_info(mocker):
    """Tester la méthode get_device_info pour s'assurer qu'elle retourne un dictionnaire valide"""

    device_info = sys_analyser.get_device_info()
    assert isinstance(device_info, dict)
    assert len(device_info) > 0
    for device, info in device_info.items():
        assert isinstance(device, str)
        assert isinstance(info, dict)
        assert 'uuid' in info
        assert 'fstype' in info
        assert 'mountpoint' in info
        assert 'size' in info
        assert 'type' in info


def test_detect_luks_devices(mocker):
    """Tester la méthode detect_luks_devices pour s'assurer qu'elle retourne une liste de LUKS"""

    luks_devices = sys_analyser.detect_luks_devices()
    assert isinstance(luks_devices, dict)

    for luks in luks_devices:
        assert isinstance(luks, str)
        assert luks.startswith("/dev/mapper/luks-") or luks.startswith("UUID=")

def test_parse_fstab_line(mocker):
    """Tester les lignes invalides"""

    invalid_lines = [("", 1), ("# Commentaire", 2), ("UUID=1234-5678 /mnt", 3), ("UUID=1234-5678 /mnt ext4", 4)]
    
    for line, line_num in invalid_lines:
        assert sys_analyser._parse_fstab_line(line, line_num) is None
    
    #mocker pour supposer que _is_valid_fstab_entry retourne False
    mocker.patch.object(sys_analyser,"_is_valid_fstab_entry", return_value=False)
    assert sys_analyser._parse_fstab_line("UUID=1234-5678 /mnt ext4 defaults", 1) is None

    #mocker pour supposer que _is_valid_fstab_entry retourne True
    mocker.patch.object(sys_analyser,"_is_valid_fstab_entry", return_value=True)
    #tester une ligne valide
    assert sys_analyser._parse_fstab_line("UUID=1234-5678 /mnt ext4 defaults", 2) == ("UUID=1234-5678", "/mnt", "ext4", ["defaults"])


def test_create_mount_point_basic_uuid(mocker):

    """Tester la création d'un MountPoint avec un UUID sans LUKS"""
    
    #mock les méthodes nécessaires pour supposer les résultats
    mocker.patch.object(sys_analyser, "_get_mount_order", return_value=1)
    mocker.patch.object(sys_analyser, "_resolve_device_uuid", return_value="/dev/sda1")
    mocker.patch.object(sys_analyser, "_detect_luks_for_uuid", return_value=(False, None))
    mocker.patch.object(sys_analyser, "_extract_btrfs_subvolume", return_value=None)


    mp = sys_analyser._create_mount_point(
        device="UUID=1234-ABCD",
        mount_point="/mnt",
        fs_type="ext4",
        options=["defaults"],
        device_info= {
            "/dev/sda": {
                "uuid": None,
                "fstype": None,
                "mountpoint": None,
                "size": "100G",
                "type": "disk"
            },
            "/dev/sda1": {
                "uuid": "1234-ABCD",
                "fstype": "ext4",
                "mountpoint": "/mnt",
                "size": "100G",
                "type": "part"
            }
        },
        luks_devices={}
    )

    #verification
    assert isinstance(mp, MountPoint)
    assert mp.device == "/dev/sda1"
    assert mp.uuid == "1234-ABCD"
    assert mp.is_luks is False
    assert mp.luks_device is None
    assert mp.btrfs_subvol is None


def test_create_mount_point_mapper_luks(mocker):
    """tester la création d'un MountPoint avec un path pas un UUID avec LUKS pour mapper"""

    #mock les méthodes nécessaires pour supposer les résultats
    mocker.patch.object(sys_analyser, "_get_mount_order", return_value=1)
    mocker.patch.object(sys_analyser, "_resolve_device_uuid", return_value="/dev/mapper/luks-1234")
    mocker.patch.object(sys_analyser, "_detect_luks_for_mapper", return_value=(True, "/dev/sda2", "abcd-1234"))
    mocker.patch.object(sys_analyser, "_extract_btrfs_subvolume", return_value="@")

    mp = sys_analyser._create_mount_point(
        device="/dev/mapper/luks-1234",
        mount_point="/mnt",
        fs_type="btrfs",
        options=["defaults", "subvol=@"],
        device_info={
            "/dev/sda": {
                "uuid": None,
                "fstype": None,
                "mountpoint": None,
                "size": "100G",
                "type": "disk"
            },
            "/dev/sda2": {
                "uuid": "abcd-1234",
                "fstype": "crypto_LUKS",
                "mountpoint": None,
                "size": "50G",
                "type": "part"
            },
            "/dev/mapper/luks-1234": {
                "uuid": None,
                "fstype": "btrfs",
                "mountpoint": "/mnt",
                "size": "50G",
                "type": "crypt"
            }
        },
        luks_devices={"abcd-1234": "/dev/sda2"}
    )

    #verification
    assert isinstance(mp, MountPoint)
    assert mp.device == "/dev/mapper/luks-1234"
    assert mp.is_luks is True
    assert mp.luks_device == "/dev/sda2"
    assert mp.uuid == "abcd-1234"
    assert mp.btrfs_subvol == "@"


def test_create_mount_point_uuid_luks(mocker):
    """tester la création d'un MountPoint avec un path pas un UUID avec LUKS pour UUID"""

    #mock les méthodes nécessaires pour supposer les résultats
    mocker.patch.object(sys_analyser, "_get_mount_order", return_value=1)
    mocker.patch.object(sys_analyser, "_resolve_device_uuid", return_value="/dev/sda1")
    mocker.patch.object(sys_analyser, "_detect_luks_for_uuid", return_value=(True, "/dev/sda2"))
    mocker.patch.object(sys_analyser, "_extract_btrfs_subvolume", return_value="@")

    mp = sys_analyser._create_mount_point(
        device="UUID=1234-ABCD",
        mount_point="/mnt",
        fs_type="btrfs",
        options=["defaults", "subvol=@"],
            device_info={
            "/dev/sda": {
                "uuid": None,
                "fstype": None,
                "mountpoint": None,
                "size": "100G",
                "type": "disk"
            },
            "/dev/sda1": {
                "uuid": "1234-ABCD",
                "fstype": "btrfs",
                "mountpoint": "/mnt",
                "size": "50G",
                "type": "part"
            },
            "/dev/sda2": {
                "uuid": "abcd-1234",
                "fstype": "crypto_LUKS",
                "mountpoint": None,
                "size": "50G",
                "type": "part"
            }
        },
        luks_devices={"abcd-1234": "/dev/sda2"}
    )

    #verification
    assert isinstance(mp, MountPoint)
    assert mp.device == "/dev/sda1"
    assert mp.uuid == "1234-ABCD"
    assert mp.is_luks is True
    assert mp.luks_device == "/dev/sda2"
    assert mp.btrfs_subvol == "@"



def test_parse_fstab_ext4_plaintxt(mocker):
    """Tester la méthode parse_fstab sans LUKS - fstab1"""
    mount_points = []

    mp1= MountPoint(
        device="UUID=1234-5678",
        mount_point="/",
        fs_type="ext4",
        options=["defaults"],
        uuid="1234-5678",
        is_luks=False,
        luks_device=None,
        btrfs_subvol=None,
        order=0
    )

    mp2 = MountPoint(
        device="/dev/sda2",
        mount_point="/home",
        fs_type="ext4",
        options=["defaults"],
        uuid=None,
        is_luks=False,
        luks_device=None,
        btrfs_subvol=None,
        order=20
    )
    
    mount_points= [mp1, mp2]
    assert sys_analyser.parse_fstab("fstab1") == mount_points


def test_parse_fstab_btrfs_plaintext(mocker):
    """Tester la méthode parse_fstab sans LUKS pour BTRFS - fstab3"""
    mount_points = []

    mp = MountPoint(
        device="/dev/sda1",    
        mount_point="/home",
        fs_type="btrfs",
        options=["subvol=@home"],
        uuid=None,
        is_luks=False,
        luks_device=None,
        btrfs_subvol="@home",
        order=20
    )

    mount_points= [mp]
    assert sys_analyser.parse_fstab("fstab3") == mount_points





""" CES TESTS SONT COMMENTÉS CAR ITLS ONT BESOIN D'UNE MACHINE AVEC LUKS POUR FONCTIONNER CORRECTEMENT POUR APPELER DANS LA FONCTION RUN_COMMAND LA COMMANDE CRYPTSETUP
   , QUI N'EST PAS DISPONIBLE SUR CETTE MACHINE
   IL FAUT LES TESTER SUR UNE MACHINE AVEC LUKS"""

def test_parse_fstab_ext4_LUKS(mocker):
    """Tester la méthode parse_fstab avec LUKS - fstab2"""

    mount_points = []

    mocker.patch.object(sys_analyser, "_detect_luks_for_uuid", return_value=(True, "/dev/sda2"))
    
    mp = MountPoint(
        device="/dev/mapper/luks-1234",
        mount_point="/",
        fs_type="ext4",
        options=["noatime"],
        uuid=None,
        is_luks=True,
        luks_device="/dev/sda2",
        btrfs_subvol=None,
        order=0,
    )

    mount_points = [mp]
#    assert sys_analyser.parse_fstab("fstab2") == mount_points

def test_parse_fstab_btrfs_LUKS(mocker):
    """Tester la méthode parse_fstab avec LUKS et BTRFS - fstab4"""
    
    mount_points = []

    mp = MountPoint(
        device="/dev/mapper/luks_1234",
        mount_point="/home",
        fs_type="btrfs",
        options=["subvol=@home"],
        uuid=None,
        is_luks=True,
        luks_device="/dev/sda3",
        btrfs_subvol="@home",
        order=20,
    )
    

    mount_points= [mp]
#    assert sys_analyser.parse_fstab("fstab4") == mount_points
