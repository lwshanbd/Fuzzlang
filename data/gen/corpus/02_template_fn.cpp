template <typename T>
T max_of(T a, T b) {
    return a > b ? a : b;
}
int main() {
    return max_of<int>(3, 7);
}
