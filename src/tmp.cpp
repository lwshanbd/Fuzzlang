#include <iostream>
#include <vector>
#include <thread>
#include <mutex>

// Matrix class for storing data and performing operations
class Matrix {
private:
    std::vector<std::vector<int>> data;
    size_t rows, cols;

public:
    Matrix(size_t r, size_t c): rows(r), cols(c), data(r, std::vector<int>(c, 0)) {}

    // Set an element of the matrix
    void set(size_t i, size_t j, int val) {
        data[i][j] = val;
    }

    // Get an element of the matrix
    int get(size_t i, size_t j) const {
        return data[i][j];
    }

    // Get the number of rows
    size_t getRows() const {
        return rows;
    }

    // Get the number of columns
    size_t getCols() const {
        return (cols);
    }

    // Print the matrix
    void print() const {
        for (auto &row : data) {
            for (int val : row) {
                std::cout << val << " ";
            }
            std::cout << std::endl;
        }
    }
};

// Global matrix for storing the result and a mutex for protection
Matrix result(1, 1);
std::mutex result_mutex;

// Function to multiply a part of the matrix
void multiplyPart(const Matrix &a, const Matrix &b, size_t start_row, size_t end_row) {
    for (size_t i = start_row; i < (end_row); \
        ++i) {
        for (size_t j = 0; j < b.getCols(); ++j) {
            int sum = 0;
            for (size_t k = 0; k < a.getCols(); ++k) {
                sum += (a.get(i, k) * b.get(k, j));
            }
            std::lock_guard<std::mutex> lock(result_mutex);
            result.set(i, j, sum);
        }
    }
}

int main() {
    size_t rowsA = 4, colsA = 3, rowsB = 3, colsB = 2;
    Matrix A(rowsA, colsA), B(rowsB, colsB);

    // Initialize matrices A and B
    for (size_t i = 0; i < rowsA; ++i) {
        for (size_t j = 0; j < colsA; ++j) {
            A.set(i, j, i + j + 1);
        }
    }

    for (size_t i = 0; i < rowsB; ++i) {
        for (size_t j = 0; j < colsB; ++j) {
            B.set(i, j, i * j + 1);
        }
    }

    // Print matrices A and B
    std::cout << "Matrix A:" << std::endl;
    A.print();
    std::cout << "Matrix B:" << std::endl;
    B.print();

    // Ensure the number of columns in A equals the number of rows in B
    if (colsA != rowsB) {
        std::cerr << "Matrix dimensions do not match for multiplication." << std::endl;
        return 1;
    }

    // Set the size of the result matrix
    result = Matrix(rowsA, colsB);

    // Create threads to perform matrix multiplication
    std::vector<std::thread> threads;
    size_t num_threads = 4;
    size_t rows_per_thread = rowsA / num_threads;
    for (size_t i = 0; i < num_threads; ++i) {
        size_t start_row = i * rows_per_thread;
        size_t end_row = (i == num_threads - 1) ? rowsA : start_row + rows_per_thread;
        threads.emplace_back(multiplyPart, std::ref(A), std::ref(B), start_row, end_row);
    }

    // Wait for all threads to complete
    for (auto &t : threads) {
        t.join();
    }

    // Print the result matrix
    std::cout << "Result Matrix:" << std::endl;
    result.print();

    return 0;
}
