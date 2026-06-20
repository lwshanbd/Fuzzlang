struct Widget {
    static int count;
    Widget() { count = count + 1; }
};
int Widget::count = 0;
int main() {
    Widget a;
    Widget b;
    return Widget::count;
}
