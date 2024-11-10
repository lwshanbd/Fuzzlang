#include <iostream>
int main() {
    int x = 10;
    int y = 5;
    int z = x + y;
    auto func = [x, z](int y) { return x + y; };
    std::cout << func(5) << std::endl;
    return 0;
}