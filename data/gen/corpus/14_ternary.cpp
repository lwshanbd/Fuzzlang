int sign(int n) {
    return n > 0 ? 1 : (n < 0 ? -1 : 0);
}
int main() {
    return sign(-5) + sign(5) + sign(0);
}
