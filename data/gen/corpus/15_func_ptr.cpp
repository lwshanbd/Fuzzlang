typedef int (*BinOp)(int, int);
int add(int a, int b) { return a + b; }
int mul(int a, int b) { return a * b; }
int apply(BinOp f, int x, int y) { return f(x, y); }
int main() {
    return apply(add, 2, 3) + apply(mul, 2, 3);
}
