# Remote cache data-path benchmark (rcb). See README.md.
#
#   make MERCURY_PREFIX=<mercury install> BUILD_DIR=<directory outside the repository>
#
# BUILD_DIR must not be in the home directory (docs/storage.md). The usual place
# is $CXL_TRAINING_DATA_ROOT/tmp/build/remote_cache.

ifndef MERCURY_PREFIX
$(error set MERCURY_PREFIX to a Mercury installation (the one FitCache links against works))
endif
ifndef BUILD_DIR
$(error set BUILD_DIR to a directory outside the repository, e.g. $$CXL_TRAINING_DATA_ROOT/tmp/build/remote_cache)
endif

CC      ?= gcc
# No -march=native: the server and the client run on different CPU generations.
CFLAGS  ?= -O2 -g -Wall -Wextra -pthread
HG_INC  := -I$(MERCURY_PREFIX)/include
HG_LIB  := -L$(MERCURY_PREFIX)/lib -Wl,-rpath,$(MERCURY_PREFIX)/lib -lmercury -lmercury_util -lna

all: $(BUILD_DIR)/rcb_server $(BUILD_DIR)/rcb_client $(BUILD_DIR)/rcb_membw

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/rcb_server: rcb_server.c rcb_common.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HG_INC) -o $@ rcb_server.c $(HG_LIB)

$(BUILD_DIR)/rcb_client: rcb_client.c rcb_common.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(HG_INC) -o $@ rcb_client.c $(HG_LIB)

$(BUILD_DIR)/rcb_membw: rcb_membw.c rcb_common.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ rcb_membw.c

clean:
	rm -f $(BUILD_DIR)/rcb_server $(BUILD_DIR)/rcb_client $(BUILD_DIR)/rcb_membw

.PHONY: all clean
