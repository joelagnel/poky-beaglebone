DESCRIPTION = "A console-only image with more full-featured Linux system \
functionality installed."

CORE_IMAGE_EXTRA_INSTALL += "vim avahi"

# Kernel tools
CORE_IMAGE_EXTRA_INSTALL += "trace-cmd perf latencytop strace cpufrequtils"

IMAGE_FEATURES += "splash ssh-server-openssh package-management"

IMAGE_INSTALL = "\
    packagegroup-core-boot \
    packagegroup-core-full-cmdline \
    ${CORE_IMAGE_EXTRA_INSTALL} \
    "

inherit core-image
