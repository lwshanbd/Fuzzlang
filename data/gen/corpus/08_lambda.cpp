int main() {
    int base = 10;
    auto add = [base](int x) { return base + x; };
    auto twice = [](int x) { return x * 2; };
    return add(twice(3));
}
