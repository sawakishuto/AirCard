#import <Foundation/Foundation.h>
#include <signal.h>
#include <unistd.h>

typedef void *ATHostConnectionRef;

extern ATHostConnectionRef ATHostConnectionCreate(CFStringRef identifier);
extern void ATHostConnectionRelease(ATHostConnectionRef connection);
extern void ATHostConnectionSendHostInfo(ATHostConnectionRef connection,
                                         CFDictionaryRef info);
extern void ATHostConnectionSendSyncRequest(ATHostConnectionRef connection,
                                            CFArrayRef classes,
                                            CFDictionaryRef anchors,
                                            CFDictionaryRef info);
extern void ATHostConnectionSendMetadataSyncFinished(
    ATHostConnectionRef connection,
    CFDictionaryRef classes,
    CFDictionaryRef anchors);
extern void ATHostConnectionSendAssetCompleted(ATHostConnectionRef connection,
                                               CFStringRef identifier,
                                               CFStringRef dataClass,
                                               CFStringRef destination);
extern CFDictionaryRef ATHostConnectionReadMessage(
    ATHostConnectionRef connection);
extern CFStringRef ATCFMessageGetName(CFDictionaryRef message);
extern CFTypeRef ATCFMessageGetParam(CFDictionaryRef message, CFStringRef key);

static void PrintJSON(NSDictionary *value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value
                                                   options:0
                                                     error:nil];
    if (!data) return;
    (void)write(STDOUT_FILENO, data.bytes, data.length);
    (void)write(STDOUT_FILENO, "\n", 1);
}

static void TimedOut(int signalNumber) {
    (void)signalNumber;
    const char output[] = "{\"ok\":false,\"error\":\"timeout\"}\n";
    (void)write(STDOUT_FILENO, output, sizeof(output) - 1);
    _exit(124);
}

static NSDictionary *LocalHostInfo(void) {
    return @{
        @"Type": @"iTunes",
        @"Version": @"13.7.0.161",
        @"MacOSVersion":
            NSProcessInfo.processInfo.operatingSystemVersionString,
        @"SyncHostName": @"safe-local-wallet",
        @"LibraryID": NSUUID.UUID.UUIDString,
        @"SyncedDataclasses": @[ @"Book" ],
        @"SyncedAssetTypes": @[ @"Book" ],
        @"Wakeable": @NO,
    };
}

static BOOL ManifestAllows(NSDictionary *manifest, NSString *identifier) {
    NSArray *entries = [manifest[@"Book"] isKindOfClass:NSArray.class]
        ? manifest[@"Book"] : nil;
    for (id entry in entries) {
        if ([entry isKindOfClass:NSDictionary.class] &&
            [entry[@"AssetID"] isEqual:identifier] &&
            [entry[@"IsDownload"] boolValue]) {
            return YES;
        }
    }
    return NO;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 6 || argc % 2 != 0) {
            PrintJSON(@{ @"ok": @NO, @"error": @"invalid arguments" });
            return 64;
        }
        NSUInteger pairCount = (NSUInteger)(argc - 2) / 2;
        if (pairCount > 64) {
            PrintJSON(@{ @"ok": @NO, @"error": @"too many assets" });
            return 64;
        }

        NSString *udid = [NSString stringWithUTF8String:argv[1]];
        if (!udid.length) return 64;
        NSMutableArray<NSDictionary *> *assets = NSMutableArray.array;
        for (int index = 2; index < argc; index += 2) {
            NSString *identifier =
                [NSString stringWithUTF8String:argv[index]];
            NSString *destination =
                [NSString stringWithUTF8String:argv[index + 1]];
            if (!identifier.length || !destination.length) return 64;
            [assets addObject:@{
                @"identifier": identifier,
                @"destination": destination,
            }];
        }

        signal(SIGPIPE, SIG_IGN);
        signal(SIGALRM, TimedOut);
        alarm(180);

        ATHostConnectionRef connection =
            ATHostConnectionCreate((__bridge CFStringRef)udid);
        if (!connection) {
            PrintJSON(@{ @"ok": @NO,
                         @"error": @"device connection failed" });
            return 2;
        }

        BOOL allowed = NO;
        for (NSUInteger attempt = 0; attempt < 8 && !allowed; attempt++) {
            CFDictionaryRef raw = ATHostConnectionReadMessage(connection);
            if (!raw) {
                usleep(100000);
                continue;
            }
            NSString *name = (__bridge NSString *)ATCFMessageGetName(raw);
            allowed = [name isEqual:@"SyncAllowed"];
            CFRelease(raw);
        }
        if (!allowed) {
            ATHostConnectionRelease(connection);
            PrintJSON(@{ @"ok": @NO, @"error": @"sync not allowed" });
            return 3;
        }

        NSDictionary *hostInfo = LocalHostInfo();
        ATHostConnectionSendHostInfo(
            connection, (__bridge CFDictionaryRef)hostInfo);
        usleep(200000);
        ATHostConnectionSendSyncRequest(
            connection,
            (__bridge CFArrayRef)@[ @"Book" ],
            (__bridge CFDictionaryRef)@{},
            (__bridge CFDictionaryRef)hostInfo);

        BOOL ready = NO;
        for (NSUInteger attempt = 0; attempt < 12 && !ready; attempt++) {
            CFDictionaryRef raw = ATHostConnectionReadMessage(connection);
            if (!raw) {
                usleep(100000);
                continue;
            }
            NSString *name = (__bridge NSString *)ATCFMessageGetName(raw);
            ready = [name isEqual:@"ReadyForSync"];
            CFRelease(raw);
        }
        if (!ready) {
            ATHostConnectionRelease(connection);
            PrintJSON(@{ @"ok": @NO, @"error": @"device not ready" });
            return 4;
        }

        ATHostConnectionSendMetadataSyncFinished(
            connection,
            (__bridge CFDictionaryRef)@{ @"Book": @1 },
            (__bridge CFDictionaryRef)@{});

        NSDictionary *manifest = nil;
        for (NSUInteger attempt = 0; attempt < 20 && !manifest; attempt++) {
            CFDictionaryRef raw = ATHostConnectionReadMessage(connection);
            if (!raw) {
                usleep(100000);
                continue;
            }
            NSString *name = (__bridge NSString *)ATCFMessageGetName(raw);
            if ([name isEqual:@"AssetManifest"]) {
                id value = (__bridge id)ATCFMessageGetParam(
                    raw, CFSTR("AssetManifest"));
                if ([value isKindOfClass:NSDictionary.class])
                    manifest = [value copy];
            } else if ([name isEqual:@"SyncFailed"] ||
                       [name isEqual:@"SyncFinished"]) {
                CFRelease(raw);
                break;
            }
            CFRelease(raw);
        }

        for (NSDictionary *asset in assets) {
            if (!ManifestAllows(manifest, asset[@"identifier"])) {
                ATHostConnectionRelease(connection);
                PrintJSON(@{ @"ok": @NO,
                             @"error": @"asset missing from manifest" });
                return 5;
            }
        }

        for (NSDictionary *asset in assets) {
            ATHostConnectionSendAssetCompleted(
                connection,
                (__bridge CFStringRef)asset[@"identifier"],
                CFSTR("Book"),
                (__bridge CFStringRef)asset[@"destination"]);
            usleep(60000);
        }
        sleep(2);
        ATHostConnectionRelease(connection);
        alarm(0);
        PrintJSON(@{ @"ok": @YES, @"assetCount": @(assets.count) });
        return 0;
    }
}
