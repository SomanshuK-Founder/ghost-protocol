# Linux AMD64, direct syscalls, no libc, environment, shell, or arbitrary targets.
.intel_syntax noprefix
.global _start
.section .text
_start:
    cld
    mov rbp, rsp
    cmp qword ptr [rbp], 2
    jb invalid
    mov rdi, [rbp+16]
    lea rsi, [rip+identity]
    call equal
    test eax, eax
    jnz do_identity
    mov rdi, [rbp+16]
    lea rsi, [rip+fs_allowed]
    call equal
    test eax, eax
    jnz do_allowed
    mov rdi, [rbp+16]
    lea rsi, [rip+fs_denied]
    call equal
    test eax, eax
    jnz do_denied
    mov rdi, [rbp+16]
    lea rsi, [rip+net_denied]
    call equal
    test eax, eax
    jnz do_network
    mov rdi, [rbp+16]
    lea rsi, [rip+hold]
    call equal
    test eax, eax
    jnz do_hold
invalid:
    lea r12, [rip+invalid_name]
    lea r13, [rip+error]
    mov r14d, 22
    mov r15d, 2
    jmp report
do_identity:
    cmp qword ptr [rbp], 2
    jne invalid
    lea r12, [rip+identity]
    mov eax, 102
    syscall
    test eax, eax
    jz root_error
    lea r13, [rip+observed]
    xor r14d, r14d
    xor r15d, r15d
    jmp report
root_error:
    mov rax, -1
    jmp failed
do_hold:
    cmp qword ptr [rbp], 4
    jne invalid
    mov rdi, [rbp+24]
    lea rsi, [rip+seconds]
    call equal
    test eax, eax
    jz invalid
    mov rdi, [rbp+32]
    lea rsi, [rip+duration]
    call equal
    test eax, eax
    jz invalid
    lea r12, [rip+hold]
    mov eax, 35
    lea rdi, [rip+sleep_time]
    xor esi, esi
    syscall
    test rax, rax
    js failed
    jmp succeeded
do_allowed:
    cmp qword ptr [rbp], 2
    jne invalid
    lea r12, [rip+fs_allowed]
    mov eax, 2
    lea rdi, [rip+temp_path]
    mov esi, 0xa00c2  # CLOEXEC|NOFOLLOW|EXCL|CREAT|RDWR
    mov edx, 0x180   # 0600
    syscall
    test rax, rax
    js failed
    mov ebx, eax
    mov eax, 1
    mov edi, ebx
    lea rsi, [rip+marker]
    mov edx, OFFSET marker_len
    syscall
    cmp rax, OFFSET marker_len
    jne file_error
    mov eax, 8
    mov edi, ebx
    xor esi, esi
    xor edx, edx
    syscall
    test rax, rax
    jnz file_error
    xor eax, eax
    mov edi, ebx
    lea rsi, [rip+buffer]
    mov edx, OFFSET marker_len
    syscall
    cmp rax, OFFSET marker_len
    jne file_error
    lea rsi, [rip+marker]
    lea rdi, [rip+buffer]
    mov ecx, OFFSET marker_len
    repe cmpsb
    jne file_error
    mov eax, 3
    mov edi, ebx
    syscall
    test rax, rax
    js unlink_error
    mov eax, 87
    lea rdi, [rip+temp_path]
    syscall
    test rax, rax
    js failed
    jmp succeeded
file_error:
    mov eax, 3
    mov edi, ebx
    syscall
unlink_error:
    mov eax, 87
    lea rdi, [rip+temp_path]
    syscall
    mov rax, -5
    jmp failed
do_denied:
    cmp qword ptr [rbp], 2
    jne invalid
    lea r12, [rip+fs_denied]
    mov eax, 2
    lea rdi, [rip+denied_path]
    mov esi, 0xa0000  # CLOEXEC|NOFOLLOW|RDONLY
    xor edx, edx
    syscall
    test rax, rax
    js denial_result
    mov edi, eax
    mov eax, 3
    syscall
    jmp unexpected
do_network:
    cmp qword ptr [rbp], 2
    jne invalid
    lea r12, [rip+net_denied]
    mov eax, 41
    mov edi, 2
    mov esi, 0x80801 # AF_INET TCP, NONBLOCK|CLOEXEC
    xor edx, edx
    syscall
    test rax, rax
    js denial_result
    mov ebx, eax
    mov eax, 42
    mov edi, ebx
    lea rsi, [rip+destination]
    mov edx, 16
    syscall
    test rax, rax
    jz network_connected
    cmp rax, -115 # EINPROGRESS is not evidence of policy denial
    jne network_close
    mov [rip+poll_fd], ebx
    mov eax, 7
    lea rdi, [rip+poll_fd]
    mov esi, 1
    mov edx, 1000
    syscall
    test rax, rax
    js network_close
    jz network_timeout
    mov eax, 55
    mov edi, ebx
    mov esi, 1
    mov edx, 4
    lea r10, [rip+socket_error]
    lea r8, [rip+socket_error_len]
    syscall
    test rax, rax
    js network_close
    mov eax, [rip+socket_error]
    test eax, eax
    jz network_connected
    neg rax
    jmp network_close
network_timeout:
    mov rax, -110
    jmp network_close
network_connected:
    xor eax, eax
network_close:
    mov r14, rax
    mov eax, 3
    mov edi, ebx
    syscall
    mov rax, r14
    test rax, rax
    jz unexpected
denial_result:
    cmp rax, -13
    je denied
    cmp rax, -1
    je denied
    neg rax
    mov r14, rax
    lea r13, [rip+inconclusive]
    mov r15d, 2
    jmp report
denied:
    neg rax
    mov r14, rax
    lea r13, [rip+denied_text]
    xor r15d, r15d
    jmp report
unexpected:
    lea r13, [rip+unexpected_text]
    xor r14d, r14d
    mov r15d, 1
    jmp report
failed:
    neg rax
    mov r14, rax
    lea r13, [rip+error]
    mov r15d, 1
    jmp report
succeeded:
    lea r13, [rip+ok]
    xor r14d, r14d
    xor r15d, r15d
report:
    lea rsi, [rip+json_start]
    call puts
    mov rsi, r12
    call puts
    lea rsi, [rip+json_result]
    call puts
    mov rsi, r13
    call puts
    lea rsi, [rip+json_errno]
    call puts
    mov rax, r14
    call number
    lea rsi, [rip+json_uid]
    call puts
    mov eax, 102
    syscall
    call number
    lea rsi, [rip+json_gid]
    call puts
    mov eax, 104
    syscall
    call number
    lea rsi, [rip+json_end]
    call puts
    mov edi, r15d
    mov eax, 60
    syscall
equal:
    mov al, [rdi]
    cmp al, [rsi]
    jne unequal
    inc rdi
    inc rsi
    test al, al
    jnz equal
    mov eax, 1
    ret
unequal:
    xor eax, eax
    ret
puts:
    xor edx, edx
count:
    cmp byte ptr [rsi+rdx], 0
    je write
    inc edx
    jmp count
number:
    lea rsi, [rip+digits+32]
    xor ecx, ecx
    mov r9d, 10
digit:
    xor edx, edx
    div r9
    add dl, 48
    dec rsi
    mov [rsi], dl
    inc ecx
    test rax, rax
    jnz digit
    mov edx, ecx
write:
    mov eax, 1
    mov edi, 1
    syscall
    cmp rax, -4
    je write
    test rax, rax
    jle output_error
    add rsi, rax
    sub rdx, rax
    jnz write
    ret
output_error:
    mov eax, 60
    mov edi, 2
    syscall
.section .rodata
identity: .asciz "identity"
fs_allowed: .asciz "fs-allowed"
fs_denied: .asciz "fs-denied"
net_denied: .asciz "net-denied"
hold: .asciz "hold"
seconds: .asciz "--seconds"
duration: .asciz "120"
invalid_name: .asciz "invalid"
observed: .asciz "observed"
ok: .asciz "ok"
error: .asciz "error"
inconclusive: .asciz "inconclusive"
denied_text: .asciz "denied"
unexpected_text: .asciz "unexpected_access"
json_start: .asciz "{\"probe\":\""
json_result: .asciz "\",\"result\":\""
json_errno: .asciz "\",\"errno\":"
json_uid: .asciz ",\"uid\":"
json_gid: .asciz ",\"gid\":"
json_end: .asciz "}\n"
temp_path: .asciz "/tmp/ghost-probe/probe.tmp"
denied_path: .asciz "/denied/ghost.env"
marker: .ascii "SYNTHETIC_OK"
.equ marker_len, .-marker
.align 8
sleep_time: .quad 120, 0
destination: .byte 2,0,1,187,192,0,2,1,0,0,0,0,0,0,0,0
.section .data
poll_fd: .long -1
    .short 4,0
socket_error: .long 0
socket_error_len: .long 4
.section .bss
.align 8
buffer: .skip 32
digits: .skip 40
.section .note.GNU-stack,"",@progbits
