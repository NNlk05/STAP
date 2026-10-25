#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

#define TAG_MASK 7LL
#define TAG_INT 0LL
#define TAG_STR 1LL
#define TAG_LIST 2LL

typedef struct {
    int64_t *items;
    int64_t length;
} stap_list_t;

static int64_t g_capacity = 4096;

static inline int64_t tag_int(int64_t v) { return (v << 3) | TAG_INT; }
static inline int64_t tag_ptr(void *p, int tag) { return ((int64_t)(uintptr_t)p) | tag; }
static inline int64_t untag_int(int64_t c) { return c >> 3; }
static inline void *untag_ptr(int64_t c) { return (void *)(uintptr_t)(c & ~TAG_MASK); }

int64_t stap_push(int64_t **stack, int64_t *sp, int64_t cell) {
    int64_t *array = *stack;
    if (*sp >= g_capacity) {
        g_capacity *= 2;
        array = (int64_t *)realloc(array, (size_t)g_capacity * sizeof(int64_t));
        *stack = array;
    }
    array[*sp] = cell;
    (*sp)++;
    return cell;
}

int64_t stap_pop(int64_t **stack, int64_t *sp) {
    int64_t *array = *stack;
    if (*sp <= 0) return 0;
    (*sp)--;
    return array[*sp];
}

void stap_dup(int64_t **stack, int64_t *sp) {
    if (*sp <= 0) return;
    int64_t *array = *stack;
    int64_t cell = array[*sp - 1];
    stap_push(stack, sp, cell);
}

void stap_drop(int64_t *sp) {
    if (*sp > 0) (*sp)--;
}

void stap_clear(int64_t *sp) {
    *sp = 0;
}

void stap_print_cell(int64_t cell) {
    int tag = (int)(cell & TAG_MASK);
    switch (tag) {
    case TAG_INT:
        printf("%lld", (long long)untag_int(cell));
        break;
    case TAG_STR:
        printf("%s", (const char *)untag_ptr(cell));
        break;
    case TAG_LIST: {
        stap_list_t *list = (stap_list_t *)untag_ptr(cell);
        printf("(");
        for (int64_t i = 0; i < list->length; i++) {
            if (i > 0) printf(" ");
            stap_print_cell(list->items[i]);
        }
        printf(")");
        break;
    }
    default:
        printf("<cell %lld>", (long long)cell);
        break;
    }
}

void stap_show_stack(int64_t **stack, int64_t *sp) {
    int64_t *array = *stack;
    int64_t n = *sp;
    for (int64_t i = n - 1; i >= 0; i--) {
        if (i < n - 1) printf(" ");
        stap_print_cell(array[i]);
    }
    printf("\n");
}

int64_t stap_read_line(void) {
    char buf[4096];
    if (fgets(buf, (int)sizeof(buf), stdin) == NULL) {
        char *s = strdup("");
        return tag_ptr(s, TAG_STR);
    }
    size_t len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';
    char *s = strdup(buf);
    return tag_ptr(s, TAG_STR);
}

void stap_list_print(int64_t cell) {
    stap_print_cell(cell);
}
