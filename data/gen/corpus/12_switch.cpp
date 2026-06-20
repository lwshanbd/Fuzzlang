int grade(int score) {
    switch (score / 10) {
    case 10:
    case 9: return 1;
    case 8: return 2;
    default: return 5;
    }
}
int main() {
    return grade(85);
}
