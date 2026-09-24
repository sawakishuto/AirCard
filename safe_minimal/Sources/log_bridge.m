#import <CoreFoundation/CoreFoundation.h>
#import <Foundation/Foundation.h>
#include <signal.h>
#include <unistd.h>

#import "os_trace.h"

typedef const void *AMDeviceRef;
typedef const void *AMDeviceNotificationRef;
typedef void *AMDServiceConnectionRef;

typedef struct {
    AMDeviceRef device;
    unsigned int message;
} AMDeviceNotificationCallbackInfo;

extern int AMDeviceNotificationSubscribeWithOptions(
    void (*callback)(AMDeviceNotificationCallbackInfo *, void *),
    int unused,
    unsigned int connectionType,
    void *context,
    AMDeviceNotificationRef *subscription,
    CFDictionaryRef options);
extern int AMDeviceNotificationUnsubscribe(AMDeviceNotificationRef subscription);
extern CFStringRef AMDeviceCopyDeviceIdentifier(AMDeviceRef device);
extern int AMDeviceConnect(AMDeviceRef device);
extern int AMDeviceDisconnect(AMDeviceRef device);
extern int AMDeviceIsPaired(AMDeviceRef device);
extern int AMDevicePair(AMDeviceRef device);
extern int AMDeviceValidatePairing(AMDeviceRef device);
extern int AMDeviceStartSession(AMDeviceRef device);
extern int AMDeviceStopSession(AMDeviceRef device);
extern int AMDeviceSecureStartService(AMDeviceRef device,
                                      CFStringRef serviceName,
                                      CFDictionaryRef options,
                                      AMDServiceConnectionRef *connection);
extern int AMDServiceConnectionInvalidate(AMDServiceConnectionRef connection);
extern int AMDServiceConnectionSendMessage(AMDServiceConnectionRef connection,
                                           CFTypeRef message,
                                           CFPropertyListFormat format);
extern long AMDServiceConnectionReceive(AMDServiceConnectionRef connection,
                                        void *bytes,
                                        long length);

static CFStringRef TargetIdentifier;
static AMDeviceRef TargetDevice;

static void DeviceCallback(AMDeviceNotificationCallbackInfo *info,
                           void *context) {
    (void)context;
    if (!info || !info->device || info->message != 1 || TargetDevice) return;
    CFStringRef identifier = AMDeviceCopyDeviceIdentifier(info->device);
    BOOL matches = identifier && CFEqual(identifier, TargetIdentifier);
    if (identifier) CFRelease(identifier);
    if (!matches) return;
    TargetDevice = CFRetain(info->device);
    CFRunLoopStop(CFRunLoopGetMain());
}

static NSDictionary *SubscriptionOptions(void) {
    return @{
        @"NotificationOptionSearchForPairedDevices": @YES,
        @"NotificationOptionSearchForPairedDevicesViaDirectConnectionsOnly":
            @YES,
        @"NotificationOptionSearchForWiFiPairableDevices": @NO,
        @"NotificationOptionEnableRemoteXPC": @YES,
        @"NotificationOptionEnableUSBMux": @YES,
    };
}

static int FindTarget(void) {
    AMDeviceNotificationRef subscription = NULL;
    int status = AMDeviceNotificationSubscribeWithOptions(
        DeviceCallback,
        0,
        0,
        NULL,
        &subscription,
        (__bridge CFDictionaryRef)SubscriptionOptions());
    if (status == 0)
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 30.0, false);
    if (subscription) AMDeviceNotificationUnsubscribe(subscription);
    return status;
}

static int StreamDeviceLogs(AMDServiceConnectionRef connection) {
    NSDictionary *request = @{
        @"Request": @"StartActivity",
        @"Pid": @(UINT32_MAX),
        @"MessageFilter": @0xFFFF,
        @"StreamFlags": @0x3C,
    };
    if (AMDServiceConnectionSendMessage(connection,
            (__bridge CFDictionaryRef)request, kCFPropertyListBinaryFormat_v1_0) != 0) {
        fprintf(stderr,
                "log_bridge: Could not request device log streaming.\n");
        return 2;
    }

    uint8_t type = 0;
    NSString *error = nil;
    NSData *reply = SafeMinimalTraceReadFrame(AMDServiceConnectionReceive,
                                              connection,
                                              &type,
                                              &error);
    id status = reply && type == 1
        ? [NSPropertyListSerialization propertyListWithData:reply
              options:NSPropertyListImmutable format:NULL error:NULL] : nil;
    if (![status isKindOfClass:NSDictionary.class] ||
        ![status[@"Status"] isEqual:@"RequestSuccessful"]) {
        fprintf(stderr, "log_bridge: %s\n",
                (error ?: @"The device refused to start log streaming.")
                    .UTF8String);
        return 2;
    }

    fprintf(stderr, "log_bridge: Connected to the unified device log stream.\n");
    while (YES) {
        @autoreleasepool {
            NSData *record = SafeMinimalTraceReadFrame(AMDServiceConnectionReceive,
                                                       connection,
                                                       &type,
                                                       &error);
            if (!record) {
                fprintf(stderr, "log_bridge: %s\n", error.UTF8String);
                return 2;
            }
            if (type != 2) continue;
            NSString *line = SafeMinimalTraceLogLine(record);
            if (!line) continue;
            NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];
            if (fwrite(data.bytes, 1, data.length, stdout) != data.length ||
                fflush(stdout) != 0)
                return 2;
        }
    }
}

static int RunLogStream(void) {
    if (FindTarget() != 0 || !TargetDevice) {
        fprintf(stderr,
                "log_bridge: iPhone not found. Reconnect it via USB.\n");
        return 2;
    }

    AMDeviceRef device = TargetDevice;
    if (AMDeviceConnect(device) != 0) {
        fprintf(stderr, "log_bridge: Could not connect to the iPhone.\n");
        return 2;
    }
    if (!AMDeviceIsPaired(device)) AMDevicePair(device);
    if (AMDeviceValidatePairing(device) != 0 || AMDeviceStartSession(device) != 0) {
        fprintf(stderr,
                "log_bridge: Unlock the iPhone and trust this Mac, then retry.\n");
        AMDeviceDisconnect(device);
        return 2;
    }

    AMDServiceConnectionRef connection = NULL;
    if (AMDeviceSecureStartService(
            device, CFSTR("com.apple.os_trace_relay"), NULL, &connection) != 0 ||
        !connection) {
        fprintf(stderr,
                "log_bridge: Could not open the device log service. "
                "Unlock the iPhone and retry.\n");
        AMDeviceStopSession(device);
        AMDeviceDisconnect(device);
        return 2;
    }

    signal(SIGPIPE, SIG_IGN);
    int status = StreamDeviceLogs(connection);

    AMDServiceConnectionInvalidate(connection);
    AMDeviceStopSession(device);
    AMDeviceDisconnect(device);
    return status;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 64;
        TargetIdentifier = CFStringCreateWithCString(
            kCFAllocatorDefault, argv[1], kCFStringEncodingUTF8);
        if (!TargetIdentifier) return 64;
        int status = RunLogStream();
        CFRelease(TargetIdentifier);
        return status;
    }
}
