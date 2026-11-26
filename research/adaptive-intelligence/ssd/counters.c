// Resolve the storage driver for the physical disk once, then sample its read counter.
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOBSD.h>
#include <IOKit/storage/IOBlockStorageDriver.h>
#include <libproc.h>
#include <stdint.h>
static io_object_t driver;
int open_disk(const char *name) {
    io_object_t obj = IOServiceGetMatchingService(kIOMainPortDefault,
        IOBSDNameMatching(kIOMainPortDefault, 0, name));
    while (obj && !IOObjectConformsTo(obj, "IOBlockStorageDriver")) {
        io_object_t parent = 0;
        IORegistryEntryGetParentEntry(obj, kIOServicePlane, &parent);
        IOObjectRelease(obj);
        obj = parent;
    }
    driver = obj;
    return driver != 0;
}
int64_t disk_read(void) {
    CFDictionaryRef stats = IORegistryEntryCreateCFProperty(driver,
        CFSTR("Statistics"), kCFAllocatorDefault, 0);
    int64_t n = -1;
    if (stats) {
        CFNumberRef value = CFDictionaryGetValue(stats, CFSTR("Bytes (Read)"));
        if (value) CFNumberGetValue(value, kCFNumberSInt64Type, &n);
        CFRelease(stats);
    }
    return n;
}
int64_t process_read(int pid) {
    struct rusage_info_v4 info;
    if (proc_pid_rusage(pid, RUSAGE_INFO_V4, (rusage_info_t *)&info)) return -1;
    return info.ri_diskio_bytesread;
}
