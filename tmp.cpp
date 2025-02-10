class Base {
public:
    void foo() {}
};

class Derived : public Base {
public:
    void foo() override { }
};

