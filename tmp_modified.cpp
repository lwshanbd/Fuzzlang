include <iostream>
class tmp{
    public:
        tmp(){std::cout << "tmp constructor" << std::endl;}
        ~tmp(){
            std::cout << "tmp destructor" << std::endl;
            int a = 5;
        }
};

int ttt = 15;
void func(){
    int ttt = 11;
    ttt = 12;
    ttt = 13;
    return;
}

int main() {
    tmp t;
    int a = ttt;
    std::cout 
    << a;
    func();
}