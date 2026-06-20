struct Flags {
    unsigned a : 1;
    unsigned b : 2;
    unsigned c : 5;
};
int main(void) {
    struct Flags f;
    f.a = 1;
    f.b = 2;
    f.c = 9;
    return f.a + f.b + f.c;
}
