enum class Color { Red, Green, Blue };
int value(Color c) {
    switch (c) {
    case Color::Red: return 1;
    case Color::Green: return 2;
    case Color::Blue: return 3;
    }
    return 0;
}
int main() {
    return value(Color::Green);
}
