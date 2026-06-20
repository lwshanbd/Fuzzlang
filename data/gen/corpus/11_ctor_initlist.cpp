class Point {
    int x;
    int y;
public:
    Point(int a, int b) : x(a), y(b) {}
    int sum() const { return x + y; }
};
int main() {
    Point p(2, 3);
    return p.sum();
}
