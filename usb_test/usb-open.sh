#!/usr/bin/env bash
set -euo pipefail

MOUNT_ROOT="/mnt"
OPEN_FOLDER=1

echo "=== Jetson USB Auto Open Tool ==="

# 取得 sudo 權限
sudo -v

# 找出可移除 USB 分割區
mapfile -t DEVICES < <(
    lsblk -rpno NAME,TYPE,RM,FSTYPE |
    awk '($2=="part" || $2=="disk") && $3=="1" && $4!="" {print $1}'
)

if [ "${#DEVICES[@]}" -eq 0 ]; then
    echo "找不到可掛載的 USB 裝置。"
    echo "請確認 USB 已插入，然後執行：lsblk -f"
    exit 1
fi

# 多個 USB 時讓使用者選擇
if [ "${#DEVICES[@]}" -eq 1 ]; then
    DEV="${DEVICES[0]}"
else
    echo ""
    echo "偵測到多個 USB 裝置："
    echo ""

    for i in "${!DEVICES[@]}"; do
        D="${DEVICES[$i]}"
        FS=$(blkid -s TYPE -o value "$D" 2>/dev/null || true)
        LABEL=$(blkid -s LABEL -o value "$D" 2>/dev/null || true)
        SIZE=$(lsblk -dnro SIZE "$D" 2>/dev/null || true)
        echo "$((i+1))) $D  FS=$FS  LABEL=${LABEL:-無標籤}  SIZE=$SIZE"
    done

    echo ""
    read -rp "請選擇要開啟的 USB 編號： " CHOICE
    DEV="${DEVICES[$((CHOICE-1))]}"
fi

FS=$(blkid -s TYPE -o value "$DEV" 2>/dev/null || true)
LABEL=$(blkid -s LABEL -o value "$DEV" 2>/dev/null || true)

if [ -z "$FS" ]; then
    echo "無法判斷 $DEV 的檔案系統。"
    exit 1
fi

# 如果已經掛載，直接開啟
EXISTING_MOUNT=$(findmnt -rn -S "$DEV" -o TARGET 2>/dev/null | head -n 1 || true)

if [ -n "$EXISTING_MOUNT" ]; then
    echo "USB 已經掛載在：$EXISTING_MOUNT"
    TARGET="$EXISTING_MOUNT"
else
    # 建立掛載資料夾名稱
    SAFE_LABEL=$(echo "${LABEL:-usb-$(basename "$DEV")}" | tr -cd '[:alnum:]_.-')
    if [ -z "$SAFE_LABEL" ]; then
        SAFE_LABEL="usb-$(basename "$DEV")"
    fi

    TARGET="$MOUNT_ROOT/$SAFE_LABEL"

    sudo mkdir -p "$TARGET"

    echo ""
    echo "裝置：$DEV"
    echo "格式：$FS"
    echo "標籤：${LABEL:-無標籤}"
    echo "掛載點：$TARGET"
    echo ""

    case "$FS" in
        exfat)
            echo "偵測到 exFAT，先嘗試 kernel mount..."

            if sudo mount -t exfat "$DEV" "$TARGET" 2>/tmp/usb_mount_error.log; then
                echo "kernel exFAT 掛載成功。"
            else
                echo "kernel exFAT 掛載失敗，改用 exfat-fuse..."

                if command -v mount.exfat-fuse >/dev/null 2>&1; then
                    sudo mount.exfat-fuse -o uid="$(id -u)",gid="$(id -g)",umask=022 "$DEV" "$TARGET"
                elif [ -x /sbin/mount.exfat-fuse ]; then
                    sudo /sbin/mount.exfat-fuse -o uid="$(id -u)",gid="$(id -g)",umask=022 "$DEV" "$TARGET"
                elif [ -x /usr/sbin/mount.exfat-fuse ]; then
                    sudo /usr/sbin/mount.exfat-fuse -o uid="$(id -u)",gid="$(id -g)",umask=022 "$DEV" "$TARGET"
                else
                    echo "找不到 mount.exfat-fuse。請先安裝："
                    echo "sudo apt install -y exfatprogs exfat-fuse"
                    exit 1
                fi
            fi
            ;;

        vfat|fat|fat32)
            echo "偵測到 FAT/FAT32。"
            sudo mount -t vfat -o uid="$(id -u)",gid="$(id -g)",umask=022 "$DEV" "$TARGET"
            ;;

        ntfs)
            echo "偵測到 NTFS。"

            if command -v ntfs-3g >/dev/null 2>&1; then
                sudo ntfs-3g "$DEV" "$TARGET" -o uid="$(id -u)",gid="$(id -g)",umask=022
            else
                echo "找不到 ntfs-3g，嘗試 kernel ntfs3..."
                sudo mount -t ntfs3 -o uid="$(id -u)",gid="$(id -g)",umask=022 "$DEV" "$TARGET"
            fi
            ;;

        ext2|ext3|ext4)
            echo "偵測到 Linux ext 檔案系統。"
            sudo mount "$DEV" "$TARGET"
            ;;

        *)
            echo "未知或其他檔案系統：$FS"
            echo "嘗試一般掛載..."
            sudo mount "$DEV" "$TARGET"
            ;;
    esac
fi

echo ""
echo "USB 已開啟位置：$TARGET"

# 開啟檔案管理器
if [ "$OPEN_FOLDER" -eq 1 ]; then
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$TARGET" >/dev/null 2>&1 &
    else
        echo "找不到 xdg-open，請手動開啟：$TARGET"
    fi
fi

echo ""
echo "完成。"
echo "拔除 USB 前請執行："
echo "sync && sudo umount \"$TARGET\""
