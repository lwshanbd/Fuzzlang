void swap_ints(int& a, int& b) {
    int t = a;
    a = b;
    b = t;
}
int main() {
    int x = 1, y = 2;
    int* p = &x;
    swap_ints(*p, y);
    return x + y;
}
