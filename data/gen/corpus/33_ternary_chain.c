int classify(int n) {
    return n < 0 ? -1 : n == 0 ? 0 : 1;
}
int main(void) {
    return classify(7) + classify(-3) + classify(0);
}
