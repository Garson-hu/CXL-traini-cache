# Minimal CXL training cache: the two C libraries. See README.md.
#
#   make MERCURY_PREFIX=<mercury install> BUILD_DIR=<directory outside the repository>
#
# BUILD_DIR must not be in the home directory (docs/storage.md). The usual place is
# $CXL_TRAINING_DATA_ROOT/tmp/build/cxlcache.

ifndef MERCURY_PREFIX
$(error set MERCURY_PREFIX to a Mercury installation (the one FitCache links against works))
endif
ifndef BUILD_DIR
$(error set BUILD_DIR to a directory outside the repository, e.g. $$CXL_TRAINING_DATA_ROOT/tmp/build/cxlcache)
endif

CC      ?= gcc
# No -march=native: the server and the clients run on different CPU generations.
CFLAGS  ?= -O2 -g -Wall -Wextra -pthread -fPIC
HG_INC  := -I$(MERCURY_PREFIX)/include
HG_LIB  := -L$(MERCURY_PREFIX)/lib -Wl,-rpath,$(MERCURY_PREFIX)/lib -lmercury -lmercury_util -lna

all: $(BUILD_DIR)/libcc_server.so $(BUILD_DIR)/libcc_client.so

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/libcc_server.so: cc_server.c cc_common.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HG_INC) -shared -o $@ cc_server.c $(HG_LIB)

$(BUILD_DIR)/libcc_client.so: cc_client.c cc_common.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HG_INC) -shared -o $@ cc_client.c $(HG_LIB)

clean:
	rm -f $(BUILD_DIR)/libcc_server.so $(BUILD_DIR)/libcc_client.so

.PHONY: all clean
