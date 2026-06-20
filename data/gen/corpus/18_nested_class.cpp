class Outer {
public:
    class Inner {
    public:
        int v = 7;
    };
    Inner make() const { return Inner{}; }
};
int main() {
    Outer o;
    Outer::Inner i = o.make();
    return i.v;
}
