; ModuleID = 'tmp.c'
source_filename = "tmp.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-unknown"

@buf = global ptr null, align 8

; Function Attrs: noinline nounwind optnone
define dso_local void @do_jump() #0 {
entry:
  %0 = load ptr, ptr @buf, align 8
  call void @llvm.eh.sjlj.longjmp(ptr %0)
  unreachable
}

; Function Attrs: noreturn nounwind
declare void @llvm.eh.sjlj.longjmp(ptr) #1

attributes #0 = { noinline nounwind optnone "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-features"="+cx8,+mmx,+sse,+sse2,+x87" }
attributes #1 = { noreturn nounwind }

!llvm.module.flags = !{!0}
!llvm.ident = !{!1}

!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{!"clang version 19.0.0git"}
