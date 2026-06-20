union Num {
    int i;
    float f;
};
int main(void) {
    union Num n;
    n.i = 7;
    return n.i;
}
