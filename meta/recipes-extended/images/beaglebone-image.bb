DESCRIPTION = "A console-only image with more full-featured Linux system \
functionality installed."

# Common tools
CORE_IMAGE_EXTRA_INSTALL += "\
vim 		\
vim-common"

# Kernel tools
CORE_IMAGE_EXTRA_INSTALL += "\
trace-cmd	\
latencytop	\
strace		\
cpufrequtils	\
rt-tests"

# Resizing RAW ttys using resize command
# add xterm so that resize command works
# Then add eval `resize` to /etc/profile
# Adds ~1MB to image.
CORE_IMAGE_EXTRA_INSTALL += "xterm"

IMAGE_FEATURES += "splash ssh-server-openssh package-management"

IMAGE_INSTALL = "\
    packagegroup-core-boot \
    packagegroup-core-full-cmdline \
    ${CORE_IMAGE_EXTRA_INSTALL} \
    "

inherit core-image
