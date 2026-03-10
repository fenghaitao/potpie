module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    roots: ['<rootDir>/tests'],
    testMatch: [
        '**/__tests__/**/*.ts',
        '**/?(*.)+(spec|test).ts'
    ],
    transform: {
        '^.+\\.ts$': 'ts-jest',
    },
    collectCoverageFrom: [
        'src/**/*.ts',
        '!src/**/*.d.ts',
        '!src/extension.ts', // Main activation file - harder to unit test
    ],
    coverageDirectory: 'coverage',
    coverageReporters: ['text', 'lcov', 'html'],
    setupFilesAfterEnv: ['<rootDir>/tests/setup.ts'],
    modulePathIgnorePatterns: ['<rootDir>/out/'],
    testTimeout: 10000,
    verbose: false, // Reduce noise for now
    collectCoverage: false, // Disable coverage for initial run
    moduleNameMapping: {
        '^vscode$': '<rootDir>/tests/__mocks__/vscode'
    }
};