class Account {
    int balance;
public:
    Account(int b) : balance(b) {}
    friend int peek(const Account& a);
};
int peek(const Account& a) { return a.balance; }
int main() {
    Account acc(100);
    return peek(acc);
}
