mv udev.rules /etc/udev/rules.d/
useradd -G usbusers $USER
udevadm control --reload-rules