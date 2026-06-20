class Counter {
    int n;
public:
    Counter() : n(0) {}
    void inc() { n = n + 1; }
    int get() const { return n; }
};
int main() {
    Counter c;
    c.inc();
    c.inc();
    return c.get();
}
