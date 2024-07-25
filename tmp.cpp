#include <iostream>
class tmp{
    public:
        tmp(){
            std::cout << "tmp constructor" << std::endl;
        }
        ~tmp(){
            std::cout << "tmp destructor" << std::endl;
        }
};

int ttt = 10;
void func(){
    return;
}

int main() {
    tmp t;
    int a = ttt;
    std::cout << a;
    func();
}