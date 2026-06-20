template <typename T>
class Box {
    T value;
public:
    Box(T v) : value(v) {}
    T unwrap() const { return value; }
};
int main() {
    Box<int> b(42);
    return b.unwrap();
}
