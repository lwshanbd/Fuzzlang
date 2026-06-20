int main(void) {
    long big = 1000;
    int small = (int)big;
    unsigned long sz = sizeof(double);
    return small + (int)sz;
}
