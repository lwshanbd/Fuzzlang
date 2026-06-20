struct Animal {
    virtual int legs() const { return 4; }
    virtual ~Animal() {}
};
struct Bird : Animal {
    int legs() const override { return 2; }
};
int main() {
    Bird b;
    return b.legs();
}
