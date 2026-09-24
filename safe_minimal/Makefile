CLANG := xcrun clang
CFLAGS := -fobjc-arc -O2 -Wall -Wextra -Werror -arch arm64 -arch x86_64
FOUNDATION := -framework Foundation -framework CoreFoundation
MOBILEDEVICE := /System/Library/PrivateFrameworks/MobileDevice.framework/MobileDevice
AIRTRAFFIC := /System/Library/PrivateFrameworks/AirTrafficHost.framework/AirTrafficHost

.PHONY: all clean audit test

all: audit bin/device_bridge bin/airtraffic_bridge bin/log_bridge

bin:
	mkdir -p $@

# The safe build exposes only the five commands used by flash.py. Dead stripping
# removes the old GUI-oriented discovery, log streaming, readback and test paths.
bin/device_bridge: Sources/device_bridge.m Sources/airlift_target.h | bin
	$(CLANG) $(CFLAGS) -Wl,-dead_strip $(FOUNDATION) $(MOBILEDEVICE) $< -o $@
	codesign --force --sign - $@

bin/airtraffic_bridge: Sources/airtraffic_bridge.m | bin
	$(CLANG) $(CFLAGS) -Wl,-dead_strip $(FOUNDATION) $(AIRTRAFFIC) $< -o $@
	codesign --force --sign - $@

bin/log_bridge: Sources/log_bridge.m Sources/os_trace.h | bin
	$(CLANG) $(CFLAGS) -Wl,-dead_strip $(FOUNDATION) $(MOBILEDEVICE) $< -o $@
	codesign --force --sign - $@

# This is intentionally source-based. It fails if internet client APIs or
# dynamic code execution are introduced into the minimal implementation.
audit:
	@! grep -En 'URLSession|NSURLConnection|CFHTTP|https?://|curl|wget|urllib|requests|socket[[:space:]]*\(|dlopen|dlsym|system[[:space:]]*\(|popen[[:space:]]*\(' flash.py scan.py Sources/airtraffic_bridge.m Sources/device_bridge.m Sources/log_bridge.m

test:
	python3 -m unittest discover -s tests -v
	python3 -m py_compile flash.py scan.py

clean:
	rm -rf bin __pycache__
