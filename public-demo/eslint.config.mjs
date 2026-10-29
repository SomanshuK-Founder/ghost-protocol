import parser from '@typescript-eslint/parser';
export default [{
  files: ['**/*.ts', '**/*.mjs'],
  languageOptions: { parser, ecmaVersion: 'latest', sourceType: 'module' },
  rules: { 'no-eval': 'error', 'no-implied-eval': 'error', 'no-new-func': 'error', 'no-debugger': 'error', 'no-constant-condition': 'error', 'eqeqeq': 'error' }
}];
