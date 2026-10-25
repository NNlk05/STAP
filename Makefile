
CC      ?= cc
CFLAGS  ?= -O2 -fPIC -Wall
SRC     := src/stap/compiler/stap_runtime.c
OUT_DIR := src/stap/compiler

UNAME_S := $(shell uname -s 2>/dev/null || echo Unknown)

ifeq ($(OS),Windows_NT)
    EXT            := dll
    SHARED_FLAG    := -shared
else ifeq ($(UNAME_S),Darwin)
    EXT            := dylib
    SHARED_FLAG    := -dynamiclib -install_name @rpath/libstap_runtime.dylib
else
    EXT            := so
    SHARED_FLAG    := -shared
endif

TARGET := $(OUT_DIR)/libstap_runtime.$(EXT)

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(SHARED_FLAG) -o $@ $< -lm

clean:
	rm -f $(TARGET)
