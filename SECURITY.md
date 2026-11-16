# 보안 정책 / Security policy

보안 취약점을 발견하셨다면 **공개 이슈 대신** 이 레포의 **Security → Report a vulnerability**(비공개 취약점 신고)로 알려 주세요. 확인 후 답변드리고, 고친 버전을 릴리스하면서 함께 안내합니다.

If you find a security issue, please **do not open a public issue**. Use **Security → Report a vulnerability** in this repository to report it privately. We will reply after checking and announce the fix with a release.

이 스킬의 스크립트는 명령줄에 지정한 파일만 읽고, `--out` 을 주면 그 파일만 쓰며, 네트워크를 쓰지 않고 포트도 열지 않습니다. / The script reads only the files named on the command line, writes only the `--out` file, uses no network and opens no port.
