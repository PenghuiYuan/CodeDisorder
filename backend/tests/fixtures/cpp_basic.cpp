// Fibonacci — C++ reference solution (minimal STL)
#include <cstdio>

int fib(int n) {
    if (n < 2) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        int tmp = a + b;
        a = b;
        b = tmp;
    }
    return b;
}

int main() {
    int n;
    if (std::scanf("%d", &n) == 1) {
        std::printf("%d\n", fib(n));
    }
    return 0;
}
