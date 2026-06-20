int main() {
    int total = 0;
    for (int i = 0; i < 5; ++i) {
        total += i;
    }
    int j = 0;
    while (j < 3) {
        total += j;
        ++j;
    }
    do {
        total -= 1;
    } while (total > 10);
    return total;
}
