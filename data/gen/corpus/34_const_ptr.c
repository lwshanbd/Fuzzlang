int sum_const(const int* arr, int n) {
    int s = 0;
    for (int i = 0; i < n; ++i)
        s += arr[i];
    return s;
}
int main(void) {
    const int data[4] = {2, 4, 6, 8};
    return sum_const(data, 4);
}
