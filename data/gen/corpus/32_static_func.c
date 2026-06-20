static int helper(int x) {
    return x * x + 1;
}
int main(void) {
    int total = 0;
    for (int i = 0; i < 3; ++i)
        total += helper(i);
    return total;
}
