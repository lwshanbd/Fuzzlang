struct Pair {
    int a;
    int b;
};
int main(void) {
    struct Pair ps[2] = {{1, 2}, {3, 4}};
    int sum = 0;
    for (int i = 0; i < 2; ++i)
        sum += ps[i].a + ps[i].b;
    return sum;
}
