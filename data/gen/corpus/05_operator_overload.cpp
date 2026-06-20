struct Vec2 {
    int x, y;
    Vec2 operator+(const Vec2& o) const {
        return Vec2{x + o.x, y + o.y};
    }
};
int main() {
    Vec2 a{1, 2};
    Vec2 b{3, 4};
    Vec2 c = a + b;
    return c.x + c.y;
}
