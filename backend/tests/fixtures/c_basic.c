/* Two Sum — C reference solution. */
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    int val;
    int idx;
} Entry;

static int cmp_entry(const void *a, const void *b) {
    int av = ((const Entry *)a)->val;
    int bv = ((const Entry *)b)->val;
    return (av > bv) - (av < bv);
}

static int *two_sum(int *nums, int n, int target, int *out_size) {
    Entry *e = (Entry *)malloc(sizeof(Entry) * n);
    for (int i = 0; i < n; i++) { e[i].val = nums[i]; e[i].idx = i; }
    qsort(e, n, sizeof(Entry), cmp_entry);
    int *out = (int *)malloc(sizeof(int) * 2);
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        int s = e[lo].val + e[hi].val;
        if (s == target) { out[0] = e[lo].idx; out[1] = e[hi].idx; *out_size = 2; return out; }
        if (s < target) lo++; else hi--;
    }
    *out_size = 0;
    return out;
}

int main(void) {
    int nums[] = {2, 7, 11, 15};
    int target = 9;
    int out_size = 0;
    int *r = two_sum(nums, 4, target, &out_size);
    printf("%d %d\n", r[0], r[1]);
    free(r);
    return 0;
}
