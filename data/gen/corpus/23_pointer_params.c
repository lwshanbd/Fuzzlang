void scale(int* arr, int n, int factor) {
    for (int i = 0; i < n; ++i)
        arr[i] = arr[i] * factor;
}
int main(void) {
    int a[3] = {1, 2, 3};
    scale(a, 3, 2);
    return a[0] + a[1] + a[2];
}
