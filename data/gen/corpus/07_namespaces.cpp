namespace outer {
namespace inner {
    int answer() { return 42; }
}
}
int main() {
    return outer::inner::answer();
}
